# (c) 2013 jw@suse.de
#
# cut strategy algorithms for a Graphtec Silhouette Cameo plotter.
#
# In order to support operation without a cutting mat, a strategic
# rearrangement of cuts is helpful.
# e.g. 
#  * With a knive, sharp turns are to be avoided. They easily rupture the paper.
#  * With some pens, the paper may become unstable if soaked with too much ink.
#    Avoid backwards or inwards strokes.
#  * In general, cut paper is fragile. Do not move backwards and cut, where other cuts 
#    were placed. We require (strict) monotonic progression along the sheet with 
#    minimal backwards movement.
#
# 2013-05-21, jw, V0.1  -- initial draught.
# 2013-05-23, jw, V0.2  -- dedup, subdivide, two options for sharp turn detectors added.


import copy
import math

presets = {
  'default': {
    'corner_detect_min_jump': 2,
    'corner_detect_dup_epsilon': 0.1,
    'monotone_allow_back_travel': 10,
    'tool_pen': False,
    'verbose': True
    },
  'nop': {
    'do_dedup': False,
    'do_subdivide': False,
    'verbose': True
  }
}

class MatFree:
  def __init__(self, preset="default", pen=False):
    """This initializer defines settings for the apply() method.
    """
    self.verbose  = False
    self.do_dedup = True
    self.do_subdivide = True

    self.preset(preset)

    self.tool_pen = pen
    self.points = []
    self.points_dict = {}
    self.paths = []

  def list_presets(self):
    return copy.deepcopy(presets)

  def preset(self, pre_name):
    if not pre_name in presets:
      raise ValueError(pre_name+': no such preset. Try "'+'", "'.join(presets.keys())+'"')
    pre = presets[pre_name]
    for k in pre.keys():
      self.__dict__[k] = pre[k]

  def export(self):
    """reverse of load(), except that the nodes are tuples of
       [x, y, { ... attrs } ]
       Most notable attributes:
       - 'sharp', it is present on nodes where the path turns by more 
          than 90 deg.
    """
    cut = []
    for path in self.paths:
      new_path = []
      for pt in path:
        new_path.append(self.points[pt])
      cut.append(new_path)
    return cut

  def pt2idx(self, x,y):
    """all points have an index, if the index differs, the point 
       is at a different locations. All points also have attributes
       stored with in the point object itself. Points that appear for the second
       time receive an attribute 'dup':1, which is incremented on further reoccurences.
    """
    class XY_a(tuple):
      def __init__(self,t):
        tuple.__init__(t)
        self.attr = {}

    k = str(x)+','+str(y)
    if k in self.points_dict:
      idx = self.points_dict[k]
      if self.verbose:
        print "%d found as dup" % idx
      if 'dup' in self.points[idx].attr:
        self.points[idx].attr['dup'] += 1
      else:
        self.points[idx].attr['dup'] = 1
    else:
      idx = len(self.points)
      self.points.append(XY_a((x,y)))
      self.points_dict[k] = idx
      self.points[idx].attr['id'] = idx
    return idx

  def load(self, cut):
    """load a sequence of paths. 
       Nodes are expected as tuples (x, y).
       We extract points into a seperate list, with attributes as a third 
       element to the tuple. Typical attributes to be added by other methods
       are refcount (if commented in), sharp (by method mark_sharp_links(), 
       ...
    """

    for path in cut:
      new_path = []
      for point in path:
        idx = self.pt2idx(point[0], point[1])

        if len(new_path) == 0 or new_path[-1] != idx or self.do_dedup == False:
          # weed out repeated points
          new_path.append(idx)
          # self.points[idx].attr['refcount'] += 1
      self.paths.append(new_path)

  def dist_sq(s, A,B):
    return (B[0]-A[0])*(B[0]-A[0]) + (B[1]-A[1])*(B[1]-A[1])

  def link_points(s):
    """add links (back and forth) between connected points.
    """
    for path in s.paths:
      A = None
      for pt in path:
        if A is not None:
          if 'link' in s.points[A].attr:
            s.points[A].attr['link'].append(pt)
          else:
            s.points[A].attr['link'] = [ pt ]

          if 'link' in s.points[pt].attr:
            s.points[pt].attr['link'].append(A)
          else:
            s.points[pt].attr['link'] = [ A ]
        A = pt

  def subdivide_segments(s, maxlen):
    """Insert addtional points along the paths, so that
       no segment is longer than maxlen
    """
    if s.do_subdivide == False:
      return
    maxlen_sq = maxlen * maxlen
    for path_idx in range(len(s.paths)):
      path = s.paths[path_idx]
      new_path = []
      for pt in path:
        if len(new_path):
          A = new_path[-1]
          dist_sq = s.dist_sq(s.points[A], s.points[pt])
          if dist_sq > maxlen_sq:
            dist = math.sqrt(dist_sq)
            nsub = int(dist/maxlen)
            seg_len = dist/float(nsub+1)
            dx = (s.points[pt][0] - s.points[A][0])/float(nsub+1)
            dy = (s.points[pt][1] - s.points[A][1])/float(nsub+1)
            if s.verbose:
              print "pt%d -- pt%d: need nsub=%d, seg_len=%g" % (A,pt,nsub,seg_len)
              print "dxdy", dx, dy, "to", (s.points[pt][0], s.points[pt][1]), "from", (s.points[A][0],s.points[A][1])
            for subdiv in range(nsub):
              sub_pt =s.pt2idx(s.points[A][0]+dx+subdiv*dx, 
                               s.points[A][1]+dy+subdiv*dy)
              new_path.append(sub_pt)
              s.points[sub_pt].attr['sub'] = True
              if s.verbose:
                print "   sub", (s.points[sub_pt][0], s.points[sub_pt][1])
        new_path.append(pt)
      s.paths[path_idx] = new_path

  def sharp_turn(s, A,B,C):
    """Given the path from A to B to C as two line segments.
       Return true, if the corner at B is more than +/- 90 degree.

       Algorithm:
       For the segment A-B, we construct the normal B-D. 
       The we test, if points A and C lie on the same side of the line(!) B-D.
       If so, it is a sharp turn.
    """
    dx = B[0]-A[0]
    dy = B[1]-A[1]
    D = (B[0]-dy, B[1]+dx)        # BD is now the normal to AB

    ## From http://www.bryceboe.com/2006/10/23/line-segment-intersection-algorithm/
    def ccw_t(A,B,C):
      """same as ccw, but expecting tuples"""
      return (C[1]-A[1])*(B[0]-A[0]) > (B[1]-A[1])*(C[0]-A[0])

    return ccw_t(A,B,D) == ccw_t(C,B,D)



  def mark_sharp_links(s):
    """walk all the points and check their links attributes, 
       to see if there are connections that form a sharp angle.
       This needs link_points() to be called earlier.
       One sharp turn per point is enough to make us careful.
       We don't track which pair of turns actually is a sharp turn, if there
       are more than two links. Those cases are rare enough to allow the inefficiency.

       TODO: can honor corner_detect_min_jump? Even if so, what should we do in the case
       where multiple points are so close together that the paper is likely to tear?
    """
    for pt in s.points:
      if 'sharp' in pt.attr:
        ## shortcut existing flags. One sharp turn per point is enough to make us careful.
        ## we don't want to track which pair of turns actually is a sharp turn, if there
        ## are more than two links per point. Those cases are rare enough 
        ## to handle them inefficiently.
        continue
      if 'link' in pt.attr:
        ll = len(pt.attr['link'])
        if ll > 4:
          ## you cannot attach 5 lines to a point without creating one sharp angle.
          pt.attr['sharp'] = True
          continue
        ## look at each pair of links once, check their angle.
        for l1 in range(ll):
          A = s.points[pt.attr['link'][l1]]
          for l2 in range(l1+1, ll):
            B = s.points[pt.attr['link'][l2]]
            if s.sharp_turn(A,pt,B):
              pt.attr['sharp'] = True
          if 'sharp' in pt.attr:
            break
      else:
        print "warning: no links in point %d. Run link_points() before mark_sharp_links()" % (pt.attr['id'])



  def mark_sharp_paths(s):
    """walk through all paths, and add an attribute { 'sharp': True } to the
       points that respond true with the sharp_turn() method.

       Caution: mark_sharp_paths() walks in the original order, which may be irrelevant 
       after reordering.

       This marks sharp turns only if paths are not intersecting or touching back. 
       Assuming link counts <= 2. Use mark_sharp_links() for the general case.
       Downside: mark_sharp_links() does not honor corner_detect_min_jump.
    """
    min_jump_sq = s.corner_detect_min_jump * s.corner_detect_min_jump
    dup_eps_sq  = s.corner_detect_dup_epsilon * s.corner_detect_dup_epsilon

    idx = 1
    A = None
    B = None 
    for path in s.paths:
      if B is not None and len(path) and s.dist_sq(B,s. points[path[0]]) > min_jump_sq:
        # disconnect the path, if we jump more than 2mm
        A = None
        B = None
        
      for iC in path:
        C = s.points[iC]
        if B is not None and s.dist_sq(B,C) < dup_eps_sq:
          # less than 0.1 mm distance: ignore the point as a duplicate.
          continue

        if A is not None and s.sharp_turn(A,B,C):
          B.attr['sharp'] = True

        A = B
        B = C
      #
    #

 
  def apply(self, cut):
    self.load(cut)
    self.subdivide_segments(self.monotone_allow_back_travel)
    self.link_points()
    self.mark_sharp_links()
    ## rules for ordering:
    ## A) If one of my links is 'sharp' and 'seen', then never cut towards it.
    ## B) When there are multiple links that are not 'seen', prefer to cut to one 
    ##    that is 'sharp' if possible. Optional rule. It may help avoid some deadlocks caused by
    ##    rule A) but not all.

    return self.export()

