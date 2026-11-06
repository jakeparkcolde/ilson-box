'use strict';
module.exports = function health(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'GET') return res.status(405).json({error:'METHOD'});
  return res.status(200).json({service:'ilson-license',status:'ok'});
};
